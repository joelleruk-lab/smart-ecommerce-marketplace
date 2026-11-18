from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db.models import Q

from .models import Category, Product, Review, SellerProfile, User


INPUT = {'class': 'input'}


class RegistrationForm(UserCreationForm):
    first_name = forms.CharField(max_length=150, required=False)
    last_name = forms.CharField(max_length=150, required=False)
    email = forms.EmailField(required=True)
    phone_number = forms.CharField(max_length=20, required=False)
    role = forms.ChoiceField(
        choices=(('CUSTOMER', 'Customer — I want to shop'), ('SELLER', 'Seller — I want to sell')),
        initial='CUSTOMER',
    )
    store_name = forms.CharField(max_length=120, required=False)
    store_description = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 3}),
        required=False,
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'first_name', 'last_name', 'email', 'phone_number', 'role')

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('An account with this email already exists.')
        return email

    def clean(self):
        cleaned = super().clean()
        role = cleaned.get('role')
        store_name = (cleaned.get('store_name') or '').strip()
        if role == 'SELLER':
            if not store_name:
                self.add_error('store_name', 'Enter a name for your store.')
            elif SellerProfile.objects.filter(store_name__iexact=store_name).exists():
                self.add_error('store_name', 'A store with this name already exists.')
        cleaned['store_name'] = store_name
        return cleaned


class LoginForm(AuthenticationForm):
    username = forms.CharField(label='Username or email')
    password = forms.CharField(label='Password', widget=forms.PasswordInput)

    def clean(self):
        identifier = (self.cleaned_data.get('username') or '').strip()
        password = self.cleaned_data.get('password')
        if identifier and password:
            match = User.objects.filter(Q(username__iexact=identifier) | Q(email__iexact=identifier)).first()
            if match:
                self.cleaned_data['username'] = match.username
        return super().clean()


class CheckoutForm(forms.Form):
    full_name = forms.CharField(max_length=150, label='Full name')
    phone_number = forms.CharField(max_length=20, label='Phone number')
    shipping_address = forms.CharField(widget=forms.Textarea(attrs={'rows': 3}), label='Delivery address')
    city = forms.CharField(max_length=100, initial='Kampala', label='City')

    def clean_phone_number(self):
        phone = self.cleaned_data['phone_number'].strip()
        digits = [char for char in phone if char.isdigit()]
        if len(digits) < 9:
            raise forms.ValidationError('Enter a valid phone number (at least 9 digits).')
        return phone


class ProductForm(forms.ModelForm):
    stock_quantity = forms.IntegerField(
        min_value=0,
        max_value=1_000_000,
        initial=1,
        label='Available stock',
    )
    image_url = forms.URLField(
        required=False,
        label='Image URL (optional)',
        help_text='Paste a Cloudinary/R2/CDN URL if you do not upload a file.',
    )

    class Meta:
        model = Product
        fields = ('name', 'category', 'description', 'price', 'low_stock_threshold', 'image', 'is_active')
        widgets = {'description': forms.Textarea(attrs={'rows': 4})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['category'].queryset = Category.objects.filter(is_active=True).order_by('name')
        if self.instance and self.instance.pk:
            inventory = getattr(self.instance, 'inventory', None)
            self.fields['stock_quantity'].initial = inventory.stock_quantity if inventory else 0

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        if len(name) < 3:
            raise forms.ValidationError('Product names need at least 3 characters.')
        return name

    def clean_description(self):
        description = self.cleaned_data['description'].strip()
        if len(description) < 10:
            raise forms.ValidationError('Describe the product in at least 10 characters.')
        return description


class StockForm(forms.Form):
    stock_quantity = forms.IntegerField(min_value=0, max_value=1_000_000, label='New stock level')


class ReviewForm(forms.ModelForm):
    rating = forms.IntegerField(
        validators=(MinValueValidator(1), MaxValueValidator(5)),
        min_value=1,
        max_value=5,
        label='Rating (1–5)',
    )

    class Meta:
        model = Review
        fields = ('rating', 'comment')
        widgets = {'comment': forms.Textarea(attrs={'rows': 3})}

    def clean_comment(self):
        comment = self.cleaned_data['comment'].strip()
        if len(comment) < 3:
            raise forms.ValidationError('Add a short comment about the product.')
        return comment


class DisputeForm(forms.Form):
    reason = forms.ChoiceField(choices=(
        ('NOT_RECEIVED', 'Item not received'),
        ('DAMAGED', 'Item damaged'),
        ('WRONG_ITEM', 'Wrong item delivered'),
        ('REFUND', 'Refund requested'),
        ('OTHER', 'Other'),
    ))
    description = forms.CharField(widget=forms.Textarea(attrs={'rows': 3}), min_length=10)


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ('name', 'icon', 'description', 'is_active')


class SellerProfileForm(forms.ModelForm):
    class Meta:
        model = SellerProfile
        fields = ('store_name', 'store_description', 'phone_number', 'address')
