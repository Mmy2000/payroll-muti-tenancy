from rest_framework import serializers

from apps.org.models import Branch, Department, Position


class BranchSerializer(serializers.ModelSerializer):
    class Meta:
        model = Branch
        fields = ["id", "code", "name", "is_head_office", "phone",
                  "address", "is_active"]


class DepartmentSerializer(serializers.ModelSerializer):
    branches = serializers.ListField(source="branch_ids", read_only=True)
    branch_names = serializers.SerializerMethodField()

    class Meta:
        model = Department
        fields = ["id", "branches", "branch_names", "code", "name", "is_active"]

    def get_branch_names(self, department) -> list[str]:
        return [row.branch.name for row in department.placements.all()]


class PositionSerializer(serializers.ModelSerializer):
    department_name = serializers.CharField(source="department.name", default="",
                                            read_only=True)

    class Meta:
        model = Position
        fields = ["id", "name", "department", "department_name", "is_active"]


class BranchWriteSerializer(serializers.Serializer):
    code = serializers.IntegerField(min_value=1, max_value=999)
    name = serializers.CharField(max_length=200)
    phone = serializers.CharField(max_length=30, required=False, allow_blank=True, default="")
    address = serializers.CharField(required=False, allow_blank=True, default="")
    is_head_office = serializers.BooleanField(required=False, allow_null=True, default=None)
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6, required=False,
                                        allow_null=True, default=None, min_value=-90,
                                        max_value=90)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6, required=False,
                                         allow_null=True, default=None, min_value=-180,
                                         max_value=180)
    radius_m = serializers.IntegerField(required=False, default=200, min_value=20,
                                        max_value=5000)


class DepartmentWriteSerializer(serializers.Serializer):
    branches = serializers.ListField(child=serializers.IntegerField(), allow_empty=False)
    code = serializers.IntegerField(min_value=1, max_value=9999, required=False,
                                    allow_null=True, default=None)
    name = serializers.CharField(max_length=120)


class PositionWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    department = serializers.IntegerField(required=False, allow_null=True, default=None)
